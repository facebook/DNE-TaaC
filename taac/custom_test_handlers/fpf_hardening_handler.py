# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Custom test handler for FPF hardening tests with long-lived collectors.

Starts 3 collectors (FSDB ribMap, HRT bulk, BGP RIB) at test-config level
(async_test_setUp) so they persist across all playbooks. Collectors register
in the module-level registry for health check access. Stops collectors and
clears the registry at async_test_tearDown.

Activated by tag "fpf_hardening" in the TestConfig.
"""

import asyncio
import json
import time
import typing as t

from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.libs.fpf.fpf_collector_registry import (
    clear_all,
    get_all_collectors,
    register_collector,
    set_test_case_start_time,
)
from taac.libs.fpf.fpf_stress_checks import (
    BgpRibCollector,
    FsdbRibmapCollector,
    HrtBulkCollector,
)

BASELINE_COLLECTION_SEC = 120


class FpfHardeningTestHandler(BaseCustomTestHandler):
    SUPPORTED_TAGS = ["fpf_hardening"]

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._collector_config: t.Dict[str, t.Any] = {}

    async def async_test_setUp(self) -> None:
        tags = getattr(self, "_tags", [])
        config_params = {}
        for tag in tags:
            if tag.startswith("fpf_hardening:"):
                try:
                    config_params = json.loads(tag.split(":", 1)[1])
                except (json.JSONDecodeError, IndexError):
                    pass

        from taac.testconfigs.fpf.fpf_hardening_common import (
            GPU_HOSTS as DEFAULT_GPU_HOSTS,
            OBSERVER_GTSWS as DEFAULT_GTSWS,
        )

        gtsws = config_params.get("gtsws", None)
        if not gtsws:
            gtsws = [
                d.name for d in self.test_topology.devices if "gtsw" in d.name.lower()
            ]
        if not gtsws:
            gtsws = DEFAULT_GTSWS

        hosts = config_params.get("hosts", None)
        if not hosts:
            hosts = [
                d.name
                for d in self.test_topology.devices
                if "rtptest" in d.name.lower()
            ]
        if not hosts:
            hosts = DEFAULT_GPU_HOSTS

        subnet_prefix = config_params.get("subnet_prefix", "5000:dd::/32")
        poll_interval_sec = config_params.get("poll_interval_sec", 5.0)
        baseline_sec = config_params.get(
            "baseline_collection_sec", BASELINE_COLLECTION_SEC
        )

        self._collector_config = {
            "gtsws": gtsws,
            "hosts": hosts,
            "subnet_prefix": subnet_prefix,
        }

        self.logger.info(
            f"[FpfHardeningHandler] Starting collectors for "
            f"{len(gtsws)} GTSWs, {len(hosts)} hosts"
        )

        fsdb_collector = FsdbRibmapCollector(
            gtsws=gtsws,
            subnet_prefix=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        fsdb_collector.set_append_mode(True)

        hrt_collector = HrtBulkCollector(
            hosts=hosts,
            supernet=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        hrt_collector.set_append_mode(True)

        bgp_collector = BgpRibCollector(
            gtsws=gtsws,
            subnet_prefix=subnet_prefix,
            interval_sec=poll_interval_sec,
        )
        bgp_collector.set_append_mode(True)

        fsdb_collector.start()
        hrt_collector.start()
        bgp_collector.start()

        register_collector("fsdb", fsdb_collector)
        register_collector("hrt", hrt_collector)
        register_collector("bgp", bgp_collector)

        self.logger.info(
            f"[FpfHardeningHandler] Collectors started. Waiting "
            f"{baseline_sec}s for baseline data collection"
        )
        await asyncio.sleep(baseline_sec)
        self.logger.info(
            "[FpfHardeningHandler] Baseline collection complete, ready for test cases"
        )

    async def async_test_case_setUp(self) -> None:
        ts = time.time()
        set_test_case_start_time(ts)
        self.logger.info(
            f"[FpfHardeningHandler] Test case start time recorded: {ts:.0f}"
        )

    async def async_test_tearDown(self) -> None:
        collectors = get_all_collectors()
        for name, collector in collectors.items():
            self.logger.info(f"[FpfHardeningHandler] Stopping {name} collector")
            try:
                await collector.stop()
            except Exception as e:
                self.logger.warning(f"[FpfHardeningHandler] Error stopping {name}: {e}")

        clear_all()
        self.logger.info(
            "[FpfHardeningHandler] All collectors stopped, registry cleared"
        )
