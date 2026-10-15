#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for custom-test-handler selection (``BaseCustomTestHandler.should_run``).

This single predicate decides whether a handler runs at all, so a silent
regression here turns a whole capability into a no-op — which is exactly what
happened to the OSS collectors before this was made explicit.

Note the patch target: ``collectors_test_handler.TAAC_OSS`` is bound at import
time from the environment (repo-wide convention), so patching ``os.environ``
has no effect here — the module constant is what must be patched.
"""

import logging
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from taac.custom_test_handlers import collectors_test_handler
from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.custom_test_handlers.collectors_test_handler import (
    CollectorsTestHandler,
    OPT_OUT_TAG,
)
from taac.custom_test_handlers.registry import (
    CUSTOM_TEST_HANDLERS,
)
from taac.libs.collectors.registry import (
    clear_collectors,
    get_collector,
    get_collector_for_host,
)


class TaggedHandler(BaseCustomTestHandler):
    SUPPORTED_TAGS = ["some_tag"]


class TestBaseShouldRun(unittest.TestCase):
    def test_selects_only_on_a_matching_tag(self) -> None:
        self.assertTrue(TaggedHandler.should_run(["some_tag"]))
        self.assertFalse(TaggedHandler.should_run(["other_tag"]))
        self.assertFalse(TaggedHandler.should_run([]))


class TestCollectorsHandlerShouldRun(unittest.TestCase):
    """The OSS collectors are baseline environment, not a per-test opt-in."""

    def test_runs_for_every_test_config_under_oss(self) -> None:
        with patch.object(collectors_test_handler, "TAAC_OSS", True):
            self.assertTrue(CollectorsTestHandler.should_run([]))
            self.assertTrue(CollectorsTestHandler.should_run(["unrelated_tag"]))

    def test_opt_out_tag_wins_under_oss(self) -> None:
        with patch.object(collectors_test_handler, "TAAC_OSS", True):
            self.assertFalse(CollectorsTestHandler.should_run([OPT_OUT_TAG]))

    def test_internal_mode_keeps_tag_based_opt_in(self) -> None:
        with patch.object(collectors_test_handler, "TAAC_OSS", False):
            self.assertFalse(CollectorsTestHandler.should_run([]))
            self.assertFalse(CollectorsTestHandler.should_run(["unrelated_tag"]))
            self.assertTrue(CollectorsTestHandler.should_run(["oss_collectors"]))


class TestHandlerIsRegistered(unittest.TestCase):
    """``should_run`` only matters if the runner ever sees the handler.

    Asserted against the registry rather than by driving
    ``TaacRunner.filter_custom_test_handlers_by_tags`` directly: importing the
    runner pulls in every TAAC test config, and some of those resolve device
    hardware over netwhoami at module scope, which no sandboxed unit test can
    do.
    """

    def test_collectors_handler_is_in_the_registry(self) -> None:
        self.assertIn(CollectorsTestHandler, CUSTOM_TEST_HANDLERS)


if __name__ == "__main__":
    unittest.main()


class _FakeCollector:
    """Stands in for the three real collectors: records start/stop, no SSH."""

    def __init__(self, driver, services, host, tmp_path, interval_sec) -> None:
        self.host = host
        self.tmp_path = tmp_path
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class TestCollectorsFanOutAcrossDuts(unittest.IsolatedAsyncioTestCase):
    """A pod test lists all four nodes as endpoints so its health checks run
    pod-wide. Before this, collectors bound to the first DUT only, so every
    collector-backed check SKIPped on the other three and the extra endpoints
    bought no coverage at all."""

    HOSTS = ["dut1", "dut2", "dut3", "dut4"]

    def _handler(self, hosts=None):
        devices = [
            SimpleNamespace(
                name=host,
                attributes=SimpleNamespace(operating_system="FBOSS"),
            )
            for host in (hosts if hosts is not None else self.HOSTS)
        ]
        return CollectorsTestHandler(
            test_topology=SimpleNamespace(devices=devices),
            logger=logging.getLogger("test"),
        )

    def _patches(self, driver_side_effect=None):
        return (
            patch.object(
                collectors_test_handler,
                "async_get_device_driver",
                AsyncMock(side_effect=driver_side_effect or (lambda host: host)),
            ),
            patch.object(collectors_test_handler, "CpuUtilizationCollector", _FakeCollector),
            patch.object(collectors_test_handler, "MemoryUtilizationCollector", _FakeCollector),
            patch.object(collectors_test_handler, "SystemdStateCollector", _FakeCollector),
        )

    def tearDown(self) -> None:
        clear_collectors()

    async def test_every_fboss_node_gets_its_own_collectors(self) -> None:
        handler = self._handler()
        with ExitStack() as stack:
            for p in self._patches():
                stack.enter_context(p)
            await handler.async_test_setUp()

        for name in ("cpu_utilization", "memory_utilization", "systemd_state"):
            for host in self.HOSTS:
                collector = get_collector_for_host(name, host)
                self.assertIsNotNone(collector, f"{name} missing for {host}")
                self.assertEqual(collector.host, host)
                self.assertTrue(collector.started)

    async def test_collectors_do_not_share_one_artifact_file(self) -> None:
        handler = self._handler()
        with ExitStack() as stack:
            for p in self._patches():
                stack.enter_context(p)
            await handler.async_test_setUp()

        collectors = {id(c): c for _, c in handler._started}
        # 4 hosts x 3 collectors, each writing its own file. The default
        # tmp_path is pid+second-stamped, so same-second starts across hosts
        # would otherwise interleave their rows into one log.
        self.assertEqual(len(collectors), 12)
        self.assertEqual(len({c.tmp_path for c in collectors.values()}), 12)

    async def test_first_dut_keeps_the_unqualified_slot(self) -> None:
        handler = self._handler()
        with ExitStack() as stack:
            for p in self._patches():
                stack.enter_context(p)
            await handler.async_test_setUp()

        self.assertIs(
            get_collector("cpu_utilization"),
            get_collector_for_host("cpu_utilization", "dut1"),
        )

    async def test_an_unreachable_node_does_not_cost_the_others(self) -> None:
        async def driver(host):
            if host == "dut3":
                raise RuntimeError("ssh refused")
            return host

        handler = self._handler()
        with ExitStack() as stack:
            for p in self._patches(driver_side_effect=driver):
                stack.enter_context(p)
            await handler.async_test_setUp()

        self.assertIsNone(get_collector_for_host("systemd_state", "dut3"))
        for host in ("dut1", "dut2", "dut4"):
            self.assertIsNotNone(get_collector_for_host("systemd_state", host))

    async def test_teardown_stops_and_clears_every_slot(self) -> None:
        handler = self._handler()
        with ExitStack() as stack:
            for p in self._patches():
                stack.enter_context(p)
            await handler.async_test_setUp()
            collectors = {id(c): c for _, c in handler._started}
            await handler.async_test_tearDown()

        self.assertTrue(all(c.stopped for c in collectors.values()))
        for name in ("cpu_utilization", "memory_utilization", "systemd_state"):
            self.assertIsNone(get_collector(name))
            for host in self.HOSTS:
                self.assertIsNone(get_collector_for_host(name, host))
