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

import unittest
from unittest.mock import patch

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
